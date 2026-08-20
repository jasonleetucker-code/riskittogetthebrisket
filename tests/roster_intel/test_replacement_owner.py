"""V1-29 — one replacement-level owner per (unit, population).

The rule this file enforces is NOT "there is one replacement level". Six
things in this tree use the word and they answer different questions in
different units; collapsing them would be the defect. What it enforces is:

* a retired implementation stays retired;
* every declared OWNER is actually consumed;
* anything declared DEAD really has no caller;
* and the census that asserts all of the above can be made to fail.

The last point is the load-bearing one. A scanner nobody has watched go red
is not evidence, so ``test_the_census_detects_a_reintroduced_duplicate``
writes a real call site and asserts the census catches it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from scripts.replacement_census import (
    ADAPTER,
    RETIRED,
    CENSUS,
    DEAD,
    DISTINCT,
    EXIT_OK,
    EXIT_VIOLATION,
    OWNER,
    RETIRED_SYMBOLS,
    build_census,
    main,
    retired_reachable,
    undeclared_owner_definitions,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_the_census_runs_clean_at_head():
    assert main(["--json-out", "/dev/null"]) == EXIT_OK


def test_retired_implementations_are_not_reachable():
    assert (
        not retired_reachable()
    ), "a replacement implementation retired by V1-29 has a production call site again"


def test_retired_implementations_are_gone_not_renamed():
    """Retirement means deletion, not a wrapper kept 'for fallback'.

    Checked against the module NAMESPACE rather than its text: the
    docstring deliberately records what was retired and why, and a text
    scan would force that explanation out of the code — the trap that
    made two earlier guards in this repo decorative.
    """
    src = (REPO / "src" / "scoring" / "replacement_level.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for symbol in RETIRED_SYMBOLS:
        assert symbol not in defined, f"{symbol} was reintroduced as a definition"


def test_every_declared_owner_is_consumed():
    """An owner nobody calls is either mis-declared or dead.

    This is what stops the census degrading into a wish list.
    """
    rows = {r.key: r for r in build_census()}
    assert rows, "the census produced no rows — it measured nothing"
    for row in rows.values():
        if row.disposition == OWNER:
            assert row.callers or row.intra, f"{row.key} is declared OWNER but nothing calls it"


def test_dead_rows_really_have_no_callers():
    for row in build_census():
        if row.disposition == DEAD:
            assert not (
                row.callers or row.intra
            ), f"{row.key} is declared DEAD but has callers: {row.callers or row.intra}"


def test_the_census_detects_a_reintroduced_duplicate(tmp_path):
    """Non-vacuity. The census must be able to fail.

    Writes a module that calls a retired symbol and asserts the scan sees
    it. Without this the "zero duplicates remain" verdict is unfalsifiable.
    """
    probe = REPO / "src" / "_v129_census_probe.py"
    probe.write_text(
        "from src.scoring.replacement_level import vorp_table\n"
        "def f(rows, slots):\n"
        "    return vorp_table(rows, slots)\n",
        encoding="utf-8",
    )
    try:
        assert retired_reachable(), "the census did NOT detect a reintroduced retired symbol"
        assert main([]) == EXIT_VIOLATION, "the census exited clean with a duplicate present"
    finally:
        probe.unlink(missing_ok=True)


def test_no_owner_symbol_is_defined_outside_its_declared_path():
    """The discovery guard, checked clean at HEAD.

    ``call_sites`` cannot tell an OWNER's real definition from a same-named
    duplicate elsewhere — it only sees the bare name in CALL position. This
    is the check that can: every OWNER symbol name must be DEFINED at
    exactly the one path its CENSUS row declares.
    """
    assert undeclared_owner_definitions() == {}


def test_the_guard_catches_a_same_named_duplicate_nobody_calls():
    """MR1, reproduced as a positive control.

    A new module defining its own ``replacement_per_game`` — the OWNER
    symbol declared for ``src/scoring/replacement_level.py`` (row B) —
    used to pass the census cleanly (exit 0, 18/18) because nothing calls
    it, so ``retired_reachable``/``build_census`` never look at it. The
    NEW guard must catch it anyway: an undeclared owner is a defect the
    moment it is defined, whether or not it is ever invoked.
    """
    probe = REPO / "src" / "league_intel" / "_v129_dup_probe.py"
    probe.write_text(
        "def replacement_per_game(rows, position):\n"
        "    return sum(r.get('points', 0.0) for r in rows) / max(len(rows), 1)\n",
        encoding="utf-8",
    )
    try:
        dups = undeclared_owner_definitions()
        assert (
            "replacement_per_game" in dups
        ), "the guard did NOT detect an undeclared duplicate definition (MR1)"
        assert "src/league_intel/_v129_dup_probe.py" in dups["replacement_per_game"]
        assert (
            main([]) == EXIT_VIOLATION
        ), "the census exited clean with an undeclared owner present"
    finally:
        probe.unlink(missing_ok=True)


def test_the_guard_catches_a_same_named_duplicate_with_a_call_site():
    """MR2, reproduced as a positive control.

    Same duplicate as MR1, but now it is live code with a real caller —
    the exact shape that used to fool ``build_census`` into reporting the
    real OWNER as consumed (the AST call scan matched the bare name
    ``replacement_per_game`` and could not tell which definition answered
    it). The guard must still fail: a second definition is the defect,
    independent of whether it is called.
    """
    probe = REPO / "src" / "league_intel" / "_v129_dup_probe.py"
    probe.write_text(
        "def replacement_per_game(rows, position):\n"
        "    return sum(r.get('points', 0.0) for r in rows) / max(len(rows), 1)\n"
        "\n"
        "\n"
        "def call_it(rows):\n"
        "    return replacement_per_game(rows, 'RB')\n",
        encoding="utf-8",
    )
    try:
        dups = undeclared_owner_definitions()
        assert (
            "replacement_per_game" in dups
        ), "the guard did NOT detect an undeclared duplicate definition with a call site (MR2)"
        assert main([]) == EXIT_VIOLATION, "the census exited clean with a called, undeclared owner"
    finally:
        probe.unlink(missing_ok=True)


def test_a_docstring_mention_does_not_trip_the_census():
    """The complementary half: history notes are not call sites.

    ``replacement_level.py``'s own docstring names ``vorp_table`` while
    explaining the retirement, and that must stay legal.
    """
    src = (REPO / "src" / "scoring" / "replacement_level.py").read_text(encoding="utf-8")
    assert "vorp_table" in src, "the fixture is stale — the docstring no longer names it"
    assert not retired_reachable(), "a docstring mention was mistaken for a call site"


def test_units_are_declared_and_distinct_rows_are_not_merged():
    """The census must keep the units apart, because that is the whole point.

    Every row declares a unit; no two rows with DIFFERENT units may claim
    the same owner. This is the executable form of the boundary table.
    """
    rows = build_census()
    for row in rows:
        assert row.unit.strip(), f"{row.key} declares no unit"
        assert row.population.strip(), f"{row.key} declares no population"
    owners = [r for r in rows if r.disposition == OWNER]
    units = [r.unit for r in owners]
    assert len(units) == len(
        set(units)
    ), f"two OWNER rows claim the same unit, which means one of them is a duplicate: {units}"


@pytest.mark.parametrize("row", CENSUS, ids=lambda r: r.key)
def test_every_row_declares_a_known_disposition(row):
    assert row.disposition in {OWNER, ADAPTER, DISTINCT, DEAD, RETIRED}
